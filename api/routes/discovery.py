import json
import mimetypes
from datetime import datetime
from typing import Optional
import functools

from fastapi import APIRouter, Depends, Request, Query
from pydantic import BaseModel, ValidationInfo, field_validator, model_validator

from config import get_settings

router = APIRouter()


class SearchQuery(BaseModel):
    term: Optional[str] = None
    contentType: Optional[list[str]] = []
    providerName: Optional[str] = None
    creatorName: Optional[str] = None
    contributorName: Optional[str] = None
    keyword: Optional[str] = None
    dataCoverageStart: Optional[int] = None
    dataCoverageEnd: Optional[int] = None
    publishedStart: Optional[int] = None
    publishedEnd: Optional[int] = None
    dateCreatedStart: Optional[int] = None
    dateCreatedEnd: Optional[int] = None
    dateModifiedStart: Optional[int] = None
    dateModifiedEnd: Optional[int] = None
    hasPartName: Optional[str] = None
    isPartOfName: Optional[str] = None
    associatedMediaName: Optional[str] = None
    fundingGrantName: Optional[str] = None
    fundingFunderName: Optional[str] = None
    creativeWorkStatus: Optional[list[str]] = []
    pageNumber: int = 1
    pageSize: int = 20

    @field_validator('*')
    def empty_str_to_none(cls, v, info: ValidationInfo):
        if info.field_name == 'term' and v:
            return v.strip()

        # Don't convert empty strings to None for list fields like contentType/creativeWorkStatus
        if info.field_name in ['contentType', 'creativeWorkStatus']:
            return v

        if isinstance(v, str) and v.strip() == '':
            return None
        return v

    @field_validator('contentType', 'creativeWorkStatus')
    def validate_list_type_fields(cls, v):
        """Ensure contentType/creativeWorkStatus is always a list and filter out empty strings"""
        if v is None:
            return []
        if isinstance(v, str):
            # Handle single string values
            return [v.strip()] if v.strip() else []
        if isinstance(v, list):
            # Filter out empty strings from list
            return [item.strip() for item in v if isinstance(item, str) and item.strip()]
        return []

    @field_validator('dataCoverageStart', 'dataCoverageEnd', 'publishedStart', 'publishedEnd', 'dateCreatedStart', 'dateCreatedEnd', 'dateModifiedStart', 'dateModifiedEnd')
    def validate_year(cls, v, info: ValidationInfo):
        if v is None:
            return v
        try:
            datetime(v, 1, 1)
        except ValueError:
            raise ValueError(f'{info.field_name} is not a valid year')

        return v

    @model_validator(mode='after')
    def validate_date_range(self):
        if self.dataCoverageStart and self.dataCoverageEnd and self.dataCoverageEnd < self.dataCoverageStart:
            raise ValueError('dataCoverageEnd must be greater or equal to dataCoverageStart')
        if self.publishedStart and self.publishedEnd and self.publishedEnd < self.publishedStart:
            raise ValueError('publishedEnd must be greater or equal to publishedStart')
        if self.dateCreatedStart and self.dateCreatedEnd and self.dateCreatedEnd < self.dateCreatedStart:
            raise ValueError('dateCreatedEnd must be greater or equal to dateCreatedStart')
        if self.dateModifiedStart and self.dateModifiedEnd and self.dateModifiedEnd < self.dateModifiedStart:
            raise ValueError('dateModifiedEnd must be greater or equal to dateModifiedStart')

    @field_validator('pageNumber', 'pageSize')
    def validate_page(cls, v, info: ValidationInfo):
        if v <= 0:
            raise ValueError(f'{info.field_name} must be greater than 0')
        return v

    @property
    def _filters(self):
        filters = []
        if self.publishedStart:
            filters.append(
                {
                    'range': {
                        'path': 'datePublished',
                        'gte': datetime(self.publishedStart, 1, 1),
                    },
                }
            )
        if self.publishedEnd:
            filters.append(
                {
                    'range': {
                        'path': 'datePublished',
                        'lt': datetime(self.publishedEnd + 1, 1, 1),  # +1 to include all of the publishedEnd year
                    },
                }
            )

        if self.dateCreatedStart:
            filters.append(
                {
                    'range': {
                        'path': 'dateCreated',
                        'gte': datetime(self.dateCreatedStart, 1, 1),
                    },
                }
            )
        if self.dateCreatedEnd:
            filters.append(
                {
                    'range': {
                        'path': 'dateCreated',
                        'lt': datetime(self.dateCreatedEnd + 1, 1, 1),  # +1 to include all of the dateCreatedEnd year
                    },
                }
            )

        if self.dateModifiedStart:
            filters.append(
                {
                    'range': {
                        'path': 'dateModified',
                        'gte': datetime(self.dateModifiedStart, 1, 1),
                    },
                }
            )
        if self.dateModifiedEnd:
            filters.append(
                {
                    'range': {
                        'path': 'dateModified',
                        'lt': datetime(self.dateModifiedEnd + 1, 1, 1),  # +1 to include all of the dateModifiedEnd year
                    },
                }
            )

        if self.dataCoverageStart:
            filters.append(
                {'range': {'path': 'temporalCoverage.startDate', 'gte': datetime(self.dataCoverageStart, 1, 1)}}
            )
        if self.dataCoverageEnd:
            filters.append(
                {'range': {'path': 'temporalCoverage.endDate', 'lt': datetime(self.dataCoverageEnd + 1, 1, 1)}}
            )

        return filters

    @property
    def _should(self):
        search_paths = ['name', 'description', 'keywords']
        should = [{'autocomplete': {'query': self.term, 'path': key, 'fuzzy': {'maxEdits': 1}}} for key in search_paths]
        return should

    @property
    def _must(self):
        must = []
        must.append({'term': {'path': 'type', 'query': "Dataset"}})
        if self.contentType and len(self.contentType) > 0:
            # Use exact term matching for each content type to ensure precise filtering
            if len(self.contentType) == 1:
                # Single content type - use term for exact match
                must.append({'term': {'path': 'additionalType', 'query': self.contentType[0]}})
            else:
                # Multiple content types - use compound OR with exact term matches
                # This ensures each content type is matched exactly, not partially
                content_type_conditions = []
                for content_type in self.contentType:
                    content_type_conditions.append({'term': {'path': 'additionalType', 'query': content_type}})
                must.append({'compound': {'should': content_type_conditions}})
        if self.creatorName:
            must.append({'text': {'path': 'creator.name', 'query': self.creatorName}})
        if self.contributorName:
            must.append({'text': {'path': 'contributor.name', 'query': self.contributorName}})
        if self.keyword:
            must.append({'text': {'path': 'keywords', 'query': self.keyword}})
        if self.providerName:
            must.append({'text': {'path': 'provider.name', 'query': self.providerName}})
        if self.hasPartName:
            must.append({'text': {'path': 'hasPart.name', 'query': self.hasPartName}})
        if self.isPartOfName:
            must.append({'text': {'path': 'isPartOf.name', 'query': self.isPartOfName}})
        if self.associatedMediaName:
            must.append({'text': {'path': 'associatedMedia.name', 'query': self.associatedMediaName}})
        if self.fundingGrantName:
            must.append({'text': {'path': 'funding.name', 'query': self.fundingGrantName}})
        if self.fundingFunderName:
            must.append({'text': {'path': 'funding.funder.name', 'query': self.fundingFunderName}})
        if self.creativeWorkStatus and len(self.creativeWorkStatus) > 0:
            # Use exact term matching for each creative work status to ensure precise filtering
            if len(self.creativeWorkStatus) == 1:
                # Single creative work status - use term for exact match on both possible paths
                must.append({
                    'compound': {
                        'should': [
                            {'term': {'path': 'creativeWorkStatus', 'query': self.creativeWorkStatus[0]}},
                            {'term': {'path': 'creativeWorkStatus.name', 'query': self.creativeWorkStatus[0]}}
                        ]
                    }
                })
            else:
                # Multiple creative work statuses - use compound OR with exact term matches
                status_conditions = []
                for status in self.creativeWorkStatus:
                    status_conditions.append({
                        'compound': {
                            'should': [
                                {'term': {'path': 'creativeWorkStatus', 'query': status}},
                                {'term': {'path': 'creativeWorkStatus.name', 'query': status}}
                            ]
                        }
                    })
                must.append({'compound': {'should': status_conditions}})
        return must


    @property
    def stages(self):
        highlightPaths = ['name', 'description', 'keywords', 'creator.name']
        stages = []
        compound = {'filter': self._filters, 'must': self._must}

        # The term is searched for in name, description, keywords and creator name
        if self.term:
            compound['should'] = [
                # https://www.mongodb.com/docs/atlas/atlas-search/score/modify-score/#std-label-scoring-boost
                {'autocomplete': {'query': self.term, 'path': 'name', 'fuzzy': {'maxEdits': 1}, 'score': { "boost": { "value": 5 } }}},
                {'autocomplete': {'query': self.term, 'path': 'description', 'fuzzy': {'maxEdits': 1}, 'score': { "boost": { "value": 3 } }}},
                {'autocomplete': {'query': self.term, 'path': 'keywords', 'fuzzy': {'maxEdits': 1}, 'score': { "boost": { "value": 3 } }}},
                {'autocomplete': {'query': self.term, 'path': 'creator.name', 'fuzzy': {'maxEdits': 1}, 'score': { "boost": { "value": 5 } }}},
            ]
        
        # Dedicated input filters. Boost the score further if matched.
        if self.creatorName:
            compound['should'] = [
                {'autocomplete': {'query': self.creatorName, 'path': 'creator.name', 'fuzzy': {'maxEdits': 1}, 'score': { "boost": { "value": 5 } }}},
            ]

        if self.contributorName:
            compound['should'] = [
                {'autocomplete': {'query': self.contributorName, 'path': 'contributor.name', 'fuzzy': {'maxEdits': 1}, 'score': { "boost": { "value": 5 } }}},
            ]

        if self.keyword:
            compound['should'] = [
                {'autocomplete': {'query': self.keyword, 'path': 'keywords', 'fuzzy': {'maxEdits': 1}, 'score': { "boost": { "value": 3 } }}},
            ]

        if self.fundingFunderName:
            compound['should'] = [
                {'autocomplete': {'query': self.fundingFunderName, 'path': 'funding.funder.name', 'fuzzy': {'maxEdits': 1}, 'score': { "boost": { "value": 3 } }}},
            ]

        search_stage = {
            '$search': {
                'index': 'fuzzy_search',
                'compound': compound,
            }
        }

        search_stage["$search"]['highlight'] = {'path': highlightPaths}

        stages.append(search_stage)

        stages.append(
            {'$set': {'score': {'$meta': 'searchScore'}, 'highlights': {'$meta': 'searchHighlights'}}},
        )

        if self.term or self.creatorName or self.keyword or self.contributorName:
            # get only results which meet minimum relevance score threshold
            stages.append({'$match': {'score': {'$gt': get_settings().search_relevance_score_threshold}}})
        
        # TODO: To exclude resource level metadata documents for now.
        stages.append({'$match': {"dateCreated": {"$not": {"$eq": None}}}})

        return stages


def get_search_query(
    term: Optional[str] = None,
    contentType: list[str] = Query(default=[]),
    providerName: Optional[str] = None,
    creatorName: Optional[str] = None,
    contributorName: Optional[str] = None,
    keyword: Optional[str] = None,
    dataCoverageStart: Optional[int] = None,
    dataCoverageEnd: Optional[int] = None,
    publishedStart: Optional[int] = None,
    publishedEnd: Optional[int] = None,
    dateCreatedStart: Optional[int] = None,
    dateCreatedEnd: Optional[int] = None,
    dateModifiedStart: Optional[int] = None,
    dateModifiedEnd: Optional[int] = None,
    hasPartName: Optional[str] = None,
    isPartOfName: Optional[str] = None,
    associatedMediaName: Optional[str] = None,
    fundingGrantName: Optional[str] = None,
    fundingFunderName: Optional[str] = None,
    creativeWorkStatus: list[str] = Query(default=[]),
    pageNumber: int = 1,
    pageSize: int = 30
) -> SearchQuery:
    """Custom dependency to handle contentType/creativeWorkStatus as both single values and lists"""

    # Create SearchQuery instance with processed parameters
    return SearchQuery(
        term=term,
        contentType=contentType,
        providerName=providerName,
        creatorName=creatorName,
        contributorName=contributorName,
        keyword=keyword,
        dataCoverageStart=dataCoverageStart,
        dataCoverageEnd=dataCoverageEnd,
        publishedStart=publishedStart,
        publishedEnd=publishedEnd,
        dateCreatedStart=dateCreatedStart,
        dateCreatedEnd=dateCreatedEnd,
        dateModifiedStart=dateModifiedStart,
        dateModifiedEnd=dateModifiedEnd,
        hasPartName=hasPartName,
        isPartOfName=isPartOfName,
        associatedMediaName=associatedMediaName,
        fundingGrantName=fundingGrantName,
        fundingFunderName=fundingFunderName,
        creativeWorkStatus=creativeWorkStatus,
        pageNumber=pageNumber,
        pageSize=pageSize
    )


@router.get("/search")
async def search(request: Request, search_query: SearchQuery = Depends(get_search_query)):
    result = await aggregate_stages(request, search_query.stages, search_query.pageNumber, search_query.pageSize)
    json_str = json.dumps(result, default=str)
    return json.loads(json_str)


async def aggregate_stages(request, stages, pageNumber=1, pageSize=20):
    stages.append({"$skip": (pageNumber - 1) * pageSize})
    stages.append({"$limit": pageSize})
    aggregation = await request.app.mongodb["discovery"].aggregate(stages).to_list(None)
    return aggregation


@router.get("/typeahead")
async def typeahead(request: Request, term: str, field: str = "term"):
    search_paths = ['name', 'description', 'keywords'] # default
    
    if field == "creator":
        search_paths = ["creator.name"]
    elif field == "contributor":
        search_paths = ["contributor.name"]
    elif field == "subject":
        search_paths = ["keywords"]
    elif field == "funder":
        search_paths = ["funding.funder.name"]

    should = [{'autocomplete': {'query': term, 'path': key, 'fuzzy': {'maxEdits': 1}}} for key in search_paths]

    stages = [
        {
            '$search': {
                'index': 'fuzzy_search',
                'compound': {'should': should},
                'highlight': {'path': search_paths},
            }
        },
        {
            '$project': {
                'name': 1,
                'description': 1,
                'keywords': 1,
                'creator': 1,
                'contributor': 1,
                'funding': 1,
                'highlights': {'$meta': 'searchHighlights'},
                '_id': 0,
            }
        },
    ]
    result = await request.app.mongodb["discovery"].aggregate(stages).to_list(20)
    return result


def to_associated_media(file):
    mime_type = mimetypes.guess_type(file.name)[0]
    extension = file.extension
    mime_type = mime_type if mime_type else extension
    size = 0
    return {
        "@type": "DataDownload",
        "name": file.name,
        "contentUrl": file.url,
        "contentSize": size,
        "sha256": file.checksum,
        "encodingFormat": mime_type,
    }


@router.get("/content-types")
async def content_types(request: Request) -> list[str]:
    existing_content_types = await request.app.db[get_settings().mongo_database]["discovery"].find().distinct('additionalType')
    return sorted(existing_content_types, key=functools.cmp_to_key(lambda c1, c2 : c1 < c2))